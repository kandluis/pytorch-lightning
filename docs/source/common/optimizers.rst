.. _optimizers:

************
Optimization
************

Lightning offers two modes for managing the optimization process:

- automatic optimization (AutoOpt)
- manual optimization

For the majority of research cases, **automatic optimization** will do the right thing for you and it is what
most users should use.

For advanced/expert users who want to do esoteric optimization schedules or techniques, use **manual optimization**.

------

Manual optimization
===================
For advanced research topics like reinforcement learning, sparse coding, or GAN research, it may be desirable
to manually manage the optimization process. To do so, do the following:

* Set the ``automatic_optimization`` property to ``False`` in your ``LightningModule`` ``__init__`` function
* Use ``self.manual_backward(loss)`` instead of ``loss.backward()``.

.. testcode:: python

    from pytorch_lightning import LightningModule

    class MyModel(LightningModule):

        def __init__(self):
            super().__init__()
            # Important: This property activate ``manual optimization`` for your model
            self.automatic_optimization = False

        def training_step(batch, batch_idx):
            opt = self.optimizers()
            loss = self.compute_loss(batch)
            self.manual_backward(loss)

.. note:: This is only recommended for experts who need ultimate flexibility. Lightning will handle only precision and accelerators logic. The users are left with ``optimizer.zero_grad()``, gradient accumulation, model toggling, etc..

.. warning:: Before 1.2, ``optimzer.step`` was calling ``optimizer.zero_grad()`` internally. From 1.2, it is left to the users expertise.

.. tip:: To perform ``accumulate_grad_batches`` with one optimizer, you can do as such.

.. tip:: ``self.optimizers()`` will return ``LightningOptimizer`` objects. You can access your own optimizer with ``optimizer.optimizer``. However, if you use your own optimizer to perform a step, Lightning won't be able to support accelerators and precision for you.

.. code-block:: python

    def __init__(self):
        self.automatic_optimization = False

    def training_step(self, batch, batch_idx):
        opt = self.optimizers()

        loss = self.compute_loss(batch)
        self.manual_backward(loss)

        # accumulate gradient batches
        if batch_idx % 2 == 0:
            opt.step()
            opt.zero_grad()

.. tip:: It is a good practice to provide the optimizer with a ``closure`` function that performs a ``forward``, ``zero_grad`` and ``backward`` of your model. It is optional for most optimizers, but makes your code compatible if you switch to an optimizer which requires a closure. See also `the PyTorch docs <https://pytorch.org/docs/stable/optim.html#optimizer-step-closure>`_.

Here is the same example as above using a ``closure``.

.. testcode:: python

    def __init__(self):
        self.automatic_optimization = False

    def training_step(self, batch, batch_idx):
        opt = self.optimizers()

        def closure():
            # Only zero_grad on the first batch to accumulate gradients
            is_first_batch_to_accumulate = batch_idx % 2 == 0
            if is_first_batch_to_accumulate:
                opt.zero_grad()

            loss = self.compute_loss(batch)
            self.manual_backward(loss)
            return loss

        opt.step(closure=closure)

.. tip:: Be careful where you call ``zero_grad`` or your model won't converge. It is good pratice to call ``zero_grad`` before ``manual_backward``.

.. testcode:: python

    import torch
    from torch import Tensor
    from pytorch_lightning import LightningModule

    class SimpleGAN(LightningModule):

        def __init__(self):
            super().__init__()
            self.G = Generator()
            self.D = Discriminator()

            # Important: This property activate ``manual optimization`` for this model
            self.automatic_optimization = False

        def sample_z(self, n) -> Tensor:
            sample = self._Z.sample((n,))
            return sample

        def sample_G(self, n) -> Tensor:
            z = self.sample_z(n)
            return self.G(z)

        def training_step(self, batch, batch_idx):
            # Implementation follows https://pytorch.org/tutorials/beginner/dcgan_faces_tutorial.html
            g_opt, d_opt = self.optimizers()

            X, _ = batch
            batch_size = X.shape[0]

            real_label = torch.ones((batch_size, 1), device=self.device)
            fake_label = torch.zeros((batch_size, 1), device=self.device)

            g_X = self.sample_G(batch_size)

            ###########################
            #  Optimize Discriminator #
            ###########################
            d_opt.zero_grad()
            d_x = self.D(X)
            errD_real = self.criterion(d_x, real_label)

            d_z = self.D(g_X.detach())
            errD_fake = self.criterion(d_z, fake_label)

            errD = (errD_real + errD_fake)

            self.manual_backward(errD)
            d_opt.step()

            #######################
            #  Optimize Generator #
            #######################
            g_opt.zero_grad()

            d_z = self.D(g_X)
            errG = self.criterion(d_z, real_label)

            self.manual_backward(errG)
            g_opt.step()

            self.log_dict({'g_loss': errG, 'd_loss': errD}, prog_bar=True)

        def configure_optimizers(self):
            g_opt = torch.optim.Adam(self.G.parameters(), lr=1e-5)
            d_opt = torch.optim.Adam(self.D.parameters(), lr=1e-5)
            return g_opt, d_opt

.. note:: ``LightningOptimizer`` provides a ``toggle_model`` function as a ``@context_manager`` for advanced users. It can be useful when performing gradient accumulation with several optimizers or training in a distributed setting.

Here is an explanation of what it does:

Considering the current optimizer as A and all other optimizers as B.
Toggling means that all parameters from B exclusive to A will have their ``requires_grad`` attribute set to ``False``. Their original state will be restored when exiting the context manager.

When performing gradient accumulation, there is no need to perform grad synchronization during the accumulation phase.
Setting ``sync_grad`` to ``False`` will block this synchronization and improve your training speed.


Here is an example for advanced use-case.

.. testcode:: python

    # Scenario for a GAN with gradient accumulation every 2 batches and optimized for multiple gpus.

    class SimpleGAN(LightningModule):

        ...

        def __init__(self):
            self.automatic_optimization = False

        def training_step(self, batch, batch_idx):
            # Implementation follows https://pytorch.org/tutorials/beginner/dcgan_faces_tutorial.html
            g_opt, d_opt = self.optimizers()

            X, _ = batch
            X.requires_grad = True
            batch_size = X.shape[0]

            real_label = torch.ones((batch_size, 1), device=self.device)
            fake_label = torch.zeros((batch_size, 1), device=self.device)

            accumulated_grad_batches = batch_idx % 2 == 0

            g_X = self.sample_G(batch_size)

            ###########################
            #  Optimize Discriminator #
            ###########################
            with d_opt.toggle_model(sync_grad=accumulated_grad_batches):
                d_x = self.D(X)
                errD_real = self.criterion(d_x, real_label)

                d_z = self.D(g_X.detach())
                errD_fake = self.criterion(d_z, fake_label)

                errD = (errD_real + errD_fake)

                self.manual_backward(errD)
                if accumulated_grad_batches:
                    d_opt.step()
                    d_opt.zero_grad()

            #######################
            #  Optimize Generator #
            #######################
            with g_opt.toggle_model(sync_grad=accumulated_grad_batches):
                d_z = self.D(g_X)
                errG = self.criterion(d_z, real_label)

                self.manual_backward(errG)
                if accumulated_grad_batches:
                    g_opt.step()
                    g_opt.zero_grad()

            self.log_dict({'g_loss': errG, 'd_loss': errD}, prog_bar=True)

------

Automatic optimization
======================
With Lightning most users don't have to think about when to call ``.zero_grad()``, ``.backward()`` and ``.step()``
since Lightning automates that for you.

.. warning::
   Before 1.2.2, ``.zero_grad()`` was called after ``.backward()`` and ``.step()`` internally.
   From 1.2.2, Lightning calls ``.zero_grad()`` before ``.backward()``.

Under the hood Lightning does the following:

.. code-block:: python

    for epoch in epochs:
        for batch in data:
            loss = model.training_step(batch, batch_idx, ...)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        for lr_scheduler in lr_schedulers:
            lr_scheduler.step()

In the case of multiple optimizers, Lightning does the following:

.. code-block:: python

    for epoch in epochs:
        for batch in data:
            for opt in optimizers:
                loss = model.training_step(batch, batch_idx, optimizer_idx)
                opt.zero_grad()
                loss.backward()
                opt.step()

        for lr_scheduler in lr_schedulers:
            lr_scheduler.step()


Learning rate scheduling
------------------------
Every optimizer you use can be paired with any `Learning Rate Scheduler <https://pytorch.org/docs/stable/optim.html#how-to-adjust-learning-rate>`_.
In the basic use-case, the scheduler (or multiple schedulers) should be returned as the second output from the ``.configure_optimizers`` method:

.. testcode::

   # no LR scheduler
   def configure_optimizers(self):
      return Adam(...)

   # Adam + LR scheduler
   def configure_optimizers(self):
      optimizer = Adam(...)
      scheduler = LambdaLR(optimizer, ...)
      return [optimizer], [scheduler]

   # Two optimizers each with a scheduler
   def configure_optimizers(self):
      optimizer1 = Adam(...)
      optimizer2 = SGD(...)
      scheduler1 = LambdaLR(optimizer1, ...)
      scheduler2 = LambdaLR(optimizer2, ...)
      return [optimizer1, optimizer2], [scheduler1, scheduler2]

When there are schedulers in which the ``.step()`` method is conditioned on a metric value (for example the
:class:`~torch.optim.lr_scheduler.ReduceLROnPlateau` scheduler), Lightning requires that the output
from ``configure_optimizers`` should be dicts, one for each optimizer, with the keyword ``monitor``
set to metric that the scheduler should be conditioned on.

.. testcode::

   # The ReduceLROnPlateau scheduler requires a monitor
   def configure_optimizers(self):
      return {
          'optimizer': Adam(...),
          'lr_scheduler': ReduceLROnPlateau(optimizer, ...),
          'monitor': 'metric_to_track'
      }

   # In the case of two optimizers, only one using the ReduceLROnPlateau scheduler
   def configure_optimizers(self):
      optimizer1 = Adam(...)
      optimizer2 = SGD(...)
      scheduler1 = ReduceLROnPlateau(optimizer1, ...)
      scheduler2 = LambdaLR(optimizer2, ...)
      return (
          {'optimizer': optimizer1, 'lr_scheduler': scheduler1, 'monitor': 'metric_to_track'},
          {'optimizer': optimizer2, 'lr_scheduler': scheduler2},
      )

.. note::
    Metrics can be made availble to condition on by simply logging it using ``self.log('metric_to_track', metric_val)``
    in your lightning module.

By default, all schedulers will be called after each epoch ends. To change this behaviour, a scheduler configuration should be
returned as a dict which can contain the following keywords:

* ``scheduler`` (required): the actual scheduler object
* ``monitor`` (optional): metric to condition
* ``interval`` (optional): either ``epoch`` (default) for stepping after each epoch ends or ``step`` for stepping
  after each optimization step
* ``frequency`` (optional): how many epochs/steps should pass between calls to ``scheduler.step()``. Default is 1,
  corresponding to updating the learning rate after every epoch/step.
* ``strict`` (optional): if set to ``True`` will enforce that value specified in ``monitor`` is available while trying
  to call ``scheduler.step()``, and stop training if not found. If ``False`` will only give a warning and continue training
  (without calling the scheduler).
* ``name`` (optional): if using the :class:`~pytorch_lightning.callbacks.LearningRateMonitor` callback to monitor the
  learning rate progress, this keyword can be used to specify a specific name the learning rate should be logged as.

.. testcode::

   # Same as the above example with additional params passed to the first scheduler
   # In this case the ReduceLROnPlateau will step after every 10 processed batches
   def configure_optimizers(self):
      optimizers = [Adam(...), SGD(...)]
      schedulers = [
         {
            'scheduler': ReduceLROnPlateau(optimizers[0], ...),
            'monitor': 'metric_to_track',
            'interval': 'step',
            'frequency': 10,
            'strict': True,
         },
         LambdaLR(optimizers[1], ...)
      ]
      return optimizers, schedulers

----------

Use multiple optimizers (like GANs)
-----------------------------------
To use multiple optimizers return two or more optimizers from :meth:`pytorch_lightning.core.LightningModule.configure_optimizers`

.. testcode::

   # one optimizer
   def configure_optimizers(self):
      return Adam(...)

   # two optimizers, no schedulers
   def configure_optimizers(self):
      return Adam(...), SGD(...)

   # Two optimizers, one scheduler for adam only
   def configure_optimizers(self):
      return [Adam(...), SGD(...)], {'scheduler': ReduceLROnPlateau(), 'monitor': 'metric_to_track'}

Lightning will call each optimizer sequentially:

.. code-block:: python

   for epoch in epochs:
       for batch in data:
           for opt in optimizers:
               loss = train_step(batch, batch_idx, optimizer_idx)
               opt.zero_grad()
               loss.backward()
               opt.step()

      for lr_scheduler in lr_schedulers:
          lr_scheduler.step()

----------

Step optimizers at arbitrary intervals
--------------------------------------
To do more interesting things with your optimizers such as learning rate warm-up or odd scheduling,
override the :meth:`optimizer_step` function.

For example, here step optimizer A every 2 batches and optimizer B every 4 batches

.. testcode::

    def optimizer_zero_grad(self, current_epoch, batch_idx, optimizer, opt_idx):
      optimizer.zero_grad()

    # Alternating schedule for optimizer steps (ie: GANs)
    def optimizer_step(self, current_epoch, batch_nb, optimizer, optimizer_idx, closure, on_tpu=False, using_native_amp=False, using_lbfgs=False):
        # update generator opt every 2 steps
        if optimizer_idx == 0:
            if batch_nb % 2 == 0 :
               optimizer.step(closure=closure)

        # update discriminator opt every 4 steps
        if optimizer_idx == 1:
            if batch_nb % 4 == 0 :
               optimizer.step(closure=closure)

Here we add a learning-rate warm up

.. testcode::

    # learning rate warm-up
    def optimizer_step(self, current_epoch, batch_nb, optimizer, optimizer_idx, closure, on_tpu=False, using_native_amp=False, using_lbfgs=False):
        # warm up lr
        if self.trainer.global_step < 500:
            lr_scale = min(1., float(self.trainer.global_step + 1) / 500.)
            for pg in optimizer.param_groups:
                pg['lr'] = lr_scale * self.hparams.learning_rate

        # update params
        optimizer.step(closure=closure)

.. note:: The default ``optimizer_step`` is relying on the internal ``LightningOptimizer`` to properly perform a step. It handles TPUs, AMP, accumulate_grad_batches and much more ...

.. testcode::

    # function hook in LightningModule
    def optimizer_step(self, current_epoch, batch_nb, optimizer, optimizer_idx, closure, on_tpu=False, using_native_amp=False, using_lbfgs=False):
      optimizer.step(closure=closure)

.. note:: To access your wrapped Optimizer from ``LightningOptimizer``, do as follow.

.. testcode::

    # function hook in LightningModule
    def optimizer_step(self, current_epoch, batch_nb, optimizer, optimizer_idx, closure, on_tpu=False, using_native_amp=False, using_lbfgs=False):

      # `optimizer is a ``LightningOptimizer`` wrapping the optimizer.
      # To access it, do as follow:
      optimizer = optimizer.optimizer

      # run step. However, it won't work on TPU, AMP, etc...
      optimizer.step(closure=closure)


----------

Using the closure functions for optimization
--------------------------------------------

When using optimization schemes such as LBFGS, the `second_order_closure` needs to be enabled. By default, this function is defined by wrapping the `training_step` and the backward steps as follows

.. warning::
   Before 1.2.2, ``.zero_grad()`` was called outside the closure internally.
   From 1.2.2, the closure calls ``.zero_grad()`` inside, so there is no need to define your own closure
   when using similar optimizers to :class:`torch.optim.LBFGS` which requires reevaluation of the loss with the closure in ``optimizer.step()``.

.. testcode::

    def second_order_closure(pl_module, split_batch, batch_idx, opt_idx, optimizer, hidden):
        # Model training step on a given batch
        result = pl_module.training_step(split_batch, batch_idx, opt_idx, hidden)

        # Model backward pass
        pl_module.backward(result, optimizer, opt_idx)

        # on_after_backward callback
        pl_module.on_after_backward(result.training_step_output, batch_idx, result.loss)

        return result

    # This default `second_order_closure` function can be enabled by passing it directly into the `optimizer.step`
    def optimizer_step(self, current_epoch, batch_nb, optimizer, optimizer_idx, second_order_closure, on_tpu=False, using_native_amp=False, using_lbfgs=False):
        # update params
        optimizer.step(second_order_closure)
